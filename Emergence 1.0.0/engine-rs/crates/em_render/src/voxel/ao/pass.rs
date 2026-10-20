//! `AmbientOcclusionPass` : occlusion ambiante tracée dans la grille voxel (L14, docs/19 § 5).
//!
//! Deux compute : (1) pour chaque pixel touché, `N` rayons cosinus de portée courte, tracés par la même traversée que le
//! tracé primaire (mode `OCCLUSION`), écrivent la fraction occultée brute ; (2) un filtre bilatéral qui ne mêle que des
//! pixels d'un même plan de voxel. L'éclairage ([`crate::LightingPass`]) lit la visibilité de l'ambiance ([`noms`]).

use super::params::AmbientOcclusionParams;
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::{MiseEnPage, entree_tampon, entree_vue};
use crate::partage::Partage;
use crate::voxel::gbuffer::noms as noms_gb;
use crate::voxel::shaders;
use crate::voxel::world::WorldBindings;
use wgpu::ShaderStages as Etage;

/// Ressources que la passe publie dans le graphe.
pub mod noms {
    use crate::graph::ResourceName;

    /// Visibilité de l'ambiance (`R32Float`) : 1 libre, 0 enfermé ; 1 aussi là où le tracé n'a rien touché.
    pub const OCCLUSION: ResourceName = ResourceName::new("voxel_ao");
    /// Occlusion brute avant filtre (`R32Uint`, empaquetée : voir [`BruteAo`]), un texel par bloc de pixels.
    pub const BRUTE: ResourceName = ResourceName::new("voxel_ao_brute");
}

/// Format de la visibilité filtrée.
pub const FORMAT_OCCLUSION: wgpu::TextureFormat = wgpu::TextureFormat::R32Float;
/// Format de l'occlusion brute.
pub const FORMAT_BRUTE: wgpu::TextureFormat = wgpu::TextureFormat::R32Uint;

/// Un texel de l'occlusion brute décodé (miroir de l'empaquetage de `voxel_ao.wgsl`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BruteAo {
    /// Fraction occultée, 0 (libre) à 255 (enfermé).
    pub occlusion: u8,
    /// Face touchée (0 à 5), `None` si le tracé n'a rien touché.
    pub face: Option<u32>,
    /// Plan de la face en voxels, relatif au voxel de la caméra.
    pub plan: i32,
}

impl BruteAo {
    /// Décalage ajouté au plan pour le stocker non signé.
    const DECALAGE: i64 = 1_048_576;

    /// Décode un mot de 32 bits de la texture brute.
    pub fn decoder(mot: u32) -> Self {
        let face = (mot >> 8) & 7;
        Self {
            occlusion: (mot & 255) as u8,
            face: (face < 6).then_some(face),
            plan: (i64::from(mot >> 11) - Self::DECALAGE) as i32,
        }
    }

    /// Fraction occultée dans [0, 1].
    pub fn fraction(&self) -> f32 {
        f32::from(self.occlusion) / 255.0
    }
}

struct Gpu {
    trace: wgpu::ComputePipeline,
    filtre: wgpu::ComputePipeline,
    groupe_trace: wgpu::BindGroup,
    groupe_filtre: wgpu::BindGroup,
    uniforme: wgpu::Buffer,
}

/// Passe d'occlusion ambiante (compute).
pub struct AmbientOcclusionPass {
    reglages: Partage<AmbientOcclusionParams>,
    monde: WorldBindings,
    gpu: Option<Gpu>,
}

impl AmbientOcclusionPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("voxel_ao");

    /// Crée la passe sur des réglages partagés avec la scène et les liaisons du monde.
    pub fn new(reglages: Partage<AmbientOcclusionParams>, monde: WorldBindings) -> Self {
        Self {
            reglages,
            monde,
            gpu: None,
        }
    }
}

fn texture(dev: &wgpu::Device, nom: &str, taille: (u32, u32), format: wgpu::TextureFormat) -> wgpu::Texture {
    dev.create_texture(&wgpu::TextureDescriptor {
        label: Some(nom),
        size: wgpu::Extent3d {
            width: taille.0,
            height: taille.1,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::STORAGE_BINDING
            | wgpu::TextureUsages::TEXTURE_BINDING
            | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    })
}

impl RenderPass for AmbientOcclusionPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, setup: &PassSetup, res: &mut Resources) {
        self.gpu = None;
        let (Some(vf), Some(hit), Some(dist)) = (
            res.buffer(noms_gb::FRAME).cloned(),
            res.view(noms_gb::HIT),
            res.view(noms_gb::DIST),
        ) else {
            log::error!("voxel_ao : le G-buffer manque (le tracé primaire doit précéder)");
            return;
        };
        let dev = g.device();
        let (r, _) = self.reglages.lire();
        let div = r.resolution_divisor();
        let taille_brute = (setup.size.0.div_ceil(div), setup.size.1.div_ceil(div));
        let brute = texture(dev, "ao brute", taille_brute, FORMAT_BRUTE);
        let vue_brute = brute.create_view(&wgpu::TextureViewDescriptor::default());
        let finale = texture(dev, "ao", setup.size, FORMAT_OCCLUSION);
        let vue_finale = finale.create_view(&wgpu::TextureViewDescriptor::default());
        res.insert_texture(noms::BRUTE, brute);
        res.insert_texture(noms::OCCLUSION, finale);
        let uniforme = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("ao uniforme"),
            size: 32,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let c = Etage::COMPUTE;
        let bgl_trace = MiseEnPage::new()
            .uniforme(c)
            .texture_uint(c)
            .texture_float_brute(c)
            .uniforme(c)
            .stockage_ecriture(c, FORMAT_BRUTE)
            .creer(dev, "ao trace bgl");
        let groupe_trace = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("ao trace groupe"),
            layout: &bgl_trace,
            entries: &[
                entree_tampon(0, &vf),
                entree_vue(1, &hit),
                entree_vue(2, &dist),
                entree_tampon(3, &uniforme),
                entree_vue(4, &vue_brute),
            ],
        });
        let bgl_filtre = MiseEnPage::new()
            .uniforme(c)
            .uniforme(c)
            .texture_uint(c)
            .texture_uint(c)
            .stockage_ecriture(c, FORMAT_OCCLUSION)
            .creer(dev, "ao filtre bgl");
        let groupe_filtre = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("ao filtre groupe"),
            layout: &bgl_filtre,
            entries: &[
                entree_tampon(0, &vf),
                entree_tampon(1, &uniforme),
                entree_vue(2, &vue_brute),
                entree_vue(3, &hit),
                entree_vue(4, &vue_finale),
            ],
        });
        let module_trace = shaders::occlusion();
        let shader_trace = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module_trace.nom()),
            source: wgpu::ShaderSource::Wgsl(module_trace.source().into()),
        });
        let layout_trace = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("ao trace layout"),
            bind_group_layouts: &[Some(&bgl_trace), Some(self.monde.layout())],
            immediate_size: 0,
        });
        let trace = dev.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("ao trace"),
            layout: Some(&layout_trace),
            module: &shader_trace,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });
        let module_filtre = shaders::occlusion_filtre();
        let shader_filtre = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module_filtre.nom()),
            source: wgpu::ShaderSource::Wgsl(module_filtre.source().into()),
        });
        let layout_filtre = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("ao filtre layout"),
            bind_group_layouts: &[Some(&bgl_filtre)],
            immediate_size: 0,
        });
        let filtre = dev.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("ao filtre"),
            layout: Some(&layout_filtre),
            module: &shader_filtre,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });
        self.gpu = Some(Gpu {
            trace,
            filtre,
            groupe_trace,
            groupe_filtre,
            uniforme,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let (r, _) = self.reglages.lire();
        let div = r.resolution_divisor();
        let cfg: [f32; 8] = [
            r.rays() as f32,
            r.range_voxels(),
            r.strength(),
            r.filter_px() as f32,
            div as f32,
            0.0,
            0.0,
            0.0,
        ];
        ctx.gpu()
            .queue()
            .write_buffer(&gpu.uniforme, 0, bytemuck::bytes_of(&cfg));
        let (l, h) = (ctx.frame().width(), ctx.frame().height());
        {
            let mut pass = ctx.compute_pass("ao tracé");
            pass.set_pipeline(&gpu.trace);
            pass.set_bind_group(0, &gpu.groupe_trace, &[]);
            pass.set_bind_group(1, self.monde.group(), &[]);
            pass.dispatch_workgroups(l.div_ceil(div).div_ceil(8), h.div_ceil(div).div_ceil(8), 1);
        }
        let mut pass = ctx.compute_pass("ao filtre");
        pass.set_pipeline(&gpu.filtre);
        pass.set_bind_group(0, &gpu.groupe_filtre, &[]);
        pass.dispatch_workgroups(l.div_ceil(8), h.div_ceil(8), 1);
    }
}
